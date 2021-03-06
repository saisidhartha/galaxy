import {
    AfterViewInit,
    Component,
    EventEmitter,
    Input,
    OnInit,
    Output,
} from '@angular/core';

import { ImportState } from '../../enums/import-state.enum';
import { Import } from '../../resources/imports/import';

import { RepositoryImportService } from '../../resources/repository-imports/repository-import.service';

import { NamespaceService } from '../../resources/namespaces/namespace.service';

import { AuthService } from '../../auth/auth.service';

import * as $ from 'jquery';

@Component({
    selector: 'app-import-detail',
    templateUrl: './import-detail.component.html',
    styleUrls: ['./import-detail.component.less'],
})
export class ImportDetailComponent implements OnInit, AfterViewInit {
    // Used to track which component is being loaded
    componentName = 'ImportDetailComponent';

    private _importTask: Import;
    private _refreshing: boolean;
    private canImport: boolean;

    scroll = false;

    ImportState: typeof ImportState = ImportState;

    @Input()
    set importTask(data: Import) {
        this.canImport = false;

        if (data) {
            this.authService.me().subscribe(me => {
                if (me.staff) {
                    this.canImport = true;
                } else {
                    this.namespaceService
                        .get(data.summary_fields.namespace.id)
                        .subscribe(namespace => {
                            for (const owner of namespace.summary_fields
                                .owners) {
                                if (me.username === owner.username) {
                                    this.canImport = true;
                                    break;
                                }
                            }
                        });
                }
            });
        }

        if (this._importTask && this.importTask.id !== data.id) {
            this.scroll = false;
            this.scrollToggled.emit(this.scroll);
        }
        this._importTask = data;
    }

    get importTask(): Import {
        return this._importTask;
    }

    @Input()
    set refreshing(data: boolean) {
        this._refreshing = data;
    }

    get refreshing(): boolean {
        return this._refreshing;
    }

    @Output()
    startedImport = new EventEmitter<Number>();
    @Output()
    scrollToggled = new EventEmitter<boolean>();

    constructor(
        private repositoryImportService: RepositoryImportService,
        private authService: AuthService,
        private namespaceService: NamespaceService,
    ) {}

    ngOnInit() {}

    ngAfterViewInit() {}

    startImport(): void {
        this.repositoryImportService
            .save({
                repository_id: this.importTask.summary_fields.repository.id,
            })
            .subscribe(response => {
                console.log(
                    `Started import for repository ${
                        this.importTask.summary_fields.repository.id
                    }`,
                );
                this.startedImport.emit(response.id);
            });
    }

    toggleScroll() {
        this.scroll = !this.scroll;
        this.scrollToggled.emit(this.scroll);
    }
}
